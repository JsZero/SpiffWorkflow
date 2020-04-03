import logging

from decimal import Decimal
import datetime

class DMNEngine:
    """
    Handles the processing of a decision table.
    """


    def __init__(self, decisionTable, debug=None):
        self.decisionTable = decisionTable
        self.debug = debug

        self.logger = logging.getLogger('DMNEngine')
        if not self.logger.handlers:
            self.logger.addHandler(logging.StreamHandler())
        self.logger.setLevel(getattr(logging, 'DEBUG' if debug else 'INFO'))

    def decide(self, *inputArgs, **inputKwargs):
        for rule in self.decisionTable.rules:
            self.logger.debug('Checking rule %s (%s)...' % (rule.id, rule.description))

            res = self.__checkRule(rule, *inputArgs, **inputKwargs)
            self.logger.debug(' Match? %s' % (res))
            if res:
                self.logger.debug(' Return %s (%s)' % (rule.id, rule.description))
                return rule

    def __checkRule(self, rule, *inputData, **inputKwargs):
        for idx, inputEntry in enumerate(rule.inputEntries):
            input = self.decisionTable.inputs[idx]

            self.logger.debug(' Checking input entry %s (%s: %s)...' % (inputEntry.id, input.label, inputEntry.operators))

            for operator, parsedValue in inputEntry.operators:
                if parsedValue is not None:
                    inputVal = DMNEngine.__getInputVal(inputEntry, idx, *inputData, **inputKwargs)
                    if isinstance(parsedValue, Decimal) and not isinstance(inputVal, Decimal):
                        self.logger.warning('Attention, you are comparing a Decimal with %r' % (type(inputVal)))

                    if operator == 'in' or operator == 'not in':
                        expression = '%r %s %s' % (parsedValue,  operator, inputVal)
                    else:
                        expression = '%s %s %r' % (inputVal, operator, parsedValue)
                    self.logger.debug(' Evaluation expression: %s' % (expression))
                    if inputData and isinstance(inputData[idx], dict):
                        locals().update(inputData[idx])
                    locals().update(inputKwargs)
                    if not eval(expression):
                        return False  # Value does not match
                    else:
                        continue  # Check the other operators/columns
                else:
                    # Empty means ignore decision value
                    self.logger.debug(' Value not defined')
                    continue  # Check the other operators/columns

        self.logger.debug(' All inputs checked')
        return True

    @staticmethod
    def __getInputVal(inputEntry, idx, *inputData, **inputKwargs):
        """
        The input of the decision method can be an expression, args or kwargs.
        It prefers an input expression per the Specification, but will fallback
        to using inputData if available.  Finally it will fall back to the
        likely very bad idea of trying to use the label.

        :param inputEntry:
        :param idx:
        :param inputData:
        :param inputKwargs:
        :return:
        """
        if inputEntry.input.expression:
            return inputEntry.input.expression
        elif inputData:
            return "%r" % inputData[idx]
        else:
            # Backwards compatibility
            return "%r" % inputKwargs[inputEntry.input.label]
